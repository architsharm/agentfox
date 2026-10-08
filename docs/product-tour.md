# Product tour

Everything the top-level README used to carry beyond the pitch: each place the policy
binds, the commands grouped by what you are trying to do, what the demo prints, how to
self-host, and what is wrapped open source versus built here. The website docs
([useagentfox.com/docs](https://useagentfox.com/docs)) cover the same ground as guides and
reference; this page is the one-file version for reading in the repository. For how the
code is put together, read [ARCHITECTURE.md](../ARCHITECTURE.md).

## Use it with your agent

**One policy set, six places it binds.** No single gateway sees every agent, and routing all of your
traffic through one is a migration rather than a control. So the policy is written once and bound
wherever your agents already run — a coding agent's hooks, an HTTP gateway, the Python SDK, the MCP
call path, a LangGraph node, the CLI. Same `Enforcer`, same packs, same decision record; what changes
is which surface it sees. Each block below says what that one actually governs, because they differ
and a claim that flattened them would be the overclaim this project exists to avoid.

### Python — one line

```python
import agentfox
agentfox.auto()
```

Every model call in the process (OpenAI chat completions, Anthropic messages, LiteLLM, LangChain —
sync, async, streamed) is traced, evaluated against policy and written to the audit log: the request
messages, the response text, and every tool call in the response (OpenAI `tool_calls`, Anthropic
`tool_use`). Each tool call goes through the same check as `/v1/guard/tool_call` before your code
can run it, with argument provenance read from the conversation — a value copied out of a
`role="tool"` message counts as tool output. A tool seen for the first time is registered with an
impact guessed from its name and marked `inferred` until you confirm it (`agentfox declare list tools`,
`agentfox declare tool`); `@fox.tool(impact=...)` in code counts as a declaration.

Nothing is blocked by the line itself: `auto()` follows each policy's own mode, `baseline` starts in
observe, and capability default-deny on tool calls applies once the agent holds its first grant.
After `agentfox init`, `tool-containment` enforces, so an irreversible tool whose arguments came from
a tool result raises `agentfox.Blocked` instead of returning the response, and your code never gets
to run it. `auto(mode="observe")` never raises. Not covered: the OpenAI Responses API, and tools
your code calls without the model asking.

### Any language — over HTTP

```bash
agentfox serve                        # gateway + control-plane API on 127.0.0.1:8080
agentfox admin users create you@example.com --token  # first operator + API token, shown once
```

Point an existing OpenAI or Anthropic client at `http://localhost:8080/v1` and change nothing else,
or ask about a single tool call:

```bash
curl -s -X POST http://localhost:8080/v1/guard/tool_call \
  -H "Authorization: Bearer $AGENTFOX_TOKEN" -H "Content-Type: application/json" \
  -d '{"agent":"payments-ops","tool":"payments.transfer",
       "arguments":{"amount":250,"currency":"USD","to":"acct_991"},
       "provenance":{"to":"tool_result","amount":"user"},
       "intent":"refund a duplicate charge"}' | jq '{verdict, approval_id}'
```

```json
{ "verdict": "escalate", "approval_id": "apr_01m376q43zby33tbsp" }
```

Flip `"to"` to `"user"` and the same call returns `allow`. Once a person approves it
(`agentfox permit approvals approve apr_…`), the same call with `"approval_id"` added runs, once;
a second retry with the same id is held again. A proxied model call that is held returns HTTP 428
with the `approval_id` in its body, so the OpenAI and Anthropic SDKs raise it as an error; resend it
with `X-AgentFox-Approval: <id>` once approved. Full surface:
[Appendix C](architecture/api-spec.md).

### LangGraph

```python
from agentfox.frameworks.langgraph import AgentFoxGuard

guard = AgentFoxGuard(agent="support-triage", intent="answer a refund question")

builder.add_node("retrieve", guard.retrieval_node(fetch_docs))   # indirect injection blocked
builder.add_node("model",    guard.model_node(call_model))        # in + out enforced, traced
builder.add_node("pay",      guard.tool_node(transfer, tool="payments.transfer"))  # the model's call, checked
```

Trace identity and retrieval taint live in graph state, so they survive checkpointing and reach the
tool node. Escalation maps to LangGraph's own `interrupt()` — one pause mechanism, not two.

### OpenAI Agents SDK

```python
from agentfox.frameworks.openai_agents import (
    agentfox_input_guardrail, agentfox_output_guardrail, guarded_function_tool,
)

@guarded_function_tool(fox, tool="payments.refund")              # checked before it runs
def refund(order_id: str, amount: float) -> str: ...

agent = Agent(name="support", tools=[refund],
              input_guardrails=[agentfox_input_guardrail(client=fox)],
              output_guardrails=[agentfox_output_guardrail(client=fox)])
```

`pip install 'agentfox[openai-agents]'`. The guardrails are the SDK's own `InputGuardrail` and
`OutputGuardrail`: they trip only on an applied block, escalation or abstention, so observe mode
changes nothing, and `output_info` carries the user message and trace id. A stopped tool call
returns a refusal to the model instead of running.

### TypeScript

`sdk/typescript/` is `@agentfox/sdk`, a dependency-free client for `/v1/guard/input`, `/output`
and `/tool_call`, with `wrapTool()` to guard a tool before it runs. Its
[README](../sdk/typescript/README.md) also shows the OpenAI client pointed at the gateway proxy.

### MCP

`agentfox scan mcp` reads the servers your MCP config declares (`.mcp.json`, `.cursor/mcp.json`,
`.claude.json`, `claude_desktop_config.json`, or `--config PATH`) without starting any of them, and
reports what each can reach, whether it is pinned, and whether a remote one carries auth; give it the
server's `tools/list` output with `--file` and it checks every tool description too. At call time the governor compares
the tool's current listing with its registered record: the org-wide definition someone reviewed, not
a copy pinned to each agent's grant. That catches the rug pull, a server that passed review on Monday
and changed on Thursday, which no scan can catch. The digest covers the name, description, input
schema and the impact annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`); a change to any of them, or a tool the server stops listing, refuses the call with
`mcp.schema_drift` and records the decision. A changed `title` or `outputSchema` raises a
`schema_drift` finding but does not hold the call. Accepting a changed definition lifts the block, so
it is a change proposal (`mcp.tool.accept`) that two different people approve, recorded in the audit
chain. A tool the server adds later is registered; if a wildcard grant such as `mcp:server/*` already
covers it, a `mcp_tool_added_under_wildcard` finding says so. An undeclared
tool becomes a discovery finding rather than an invisible call, and results are evaluated on the
`tool_result` surface with the taint propagated, so an argument later derived from an MCP result
cannot exceed the ceiling for tool-sourced data.

### Claude Code — three hook points

```bash
agentfox admin hooks daemon                             # the warm process, once
agentfox admin hooks install --agent my-agent --write   # writes .claude/settings.json
```

Three events, because one event is one surface:

| Event | What it sees | What a refusal does |
| --- | --- | --- |
| `UserPromptSubmit` | the turn you submitted | stops it reaching the model |
| `PreToolUse` | the call about to run | stops the call, or rewrites its arguments |
| `PostToolUse` | what the tool returned | **cannot** withdraw the call; tells the model the result is untrusted |

That third row is the one worth reading twice. By the time `PostToolUse` fires the side effect has
happened, and we say so rather than reporting the event as a gate — `agentfox admin hooks status` prints
the same line, per event, with how it was established and against which version. The claims come from
[`hooks/capability.py`](../src/agentfox/hooks/capability.py): `PreToolUse` and `PostToolUse` were probed
against a live session, `UserPromptSubmit` was read in the shipped bundle, and an event nobody has
checked has no row at all.

A hook runs in a process the harness creates and destroys per call, so it talks to a warm daemon over
a private Unix socket: 3.9s cold, about 6ms warm. `hooks install --write` also sets up a working
baseline: it registers the agent (in `development` unless `--env` says otherwise), declares Claude
Code's built-in tools with their real impact and grants them to it (`--no-grant` skips that), so
ordinary work is not refused by default deny. Other tools, such as MCP servers, get no grant;
`agentfox policy proposals from-traffic --agent <slug>` proposes them from what the agent was seen to
call. And it binds the pack built for this job, `coding-agent`, to the agent it just installed and to
no other — so a support bot in the
same deployment is never told it is in "a coding session". `agentfox init` binds the pack for any agent
already named in `.claude/settings.json`, and skips the pack when there is none. It ships in observe;
promote it when its decisions look right:

```bash
agentfox policy enforce coding-agent
```

[`plugins/claude-code/`](../plugins/claude-code/) additionally packages the product as a Claude Code plugin: skills, slash commands,
subagents and an MCP server:

```bash
claude plugin marketplace add architsharm/agentfox
```

**What a hook is not.** It governs the agent on this machine. Anything not going through this harness
is not going through this, and a session that runs in the vendor's cloud rather than on the laptop is
not visible to it at all.

Turning enforcement on for model traffic is one step: `agentfox policy enforce baseline`. Everything
before it is safe to run, and `agentfox policy observe baseline` puts it back.

## Tracking without anyone running a command

A scan is a snapshot. Connect a GitHub repository, a hosted API's OpenAPI document or an MCP server
once and AgentFox keeps re-checking it: every few hours, and on every push once the GitHub webhook
is registered. Each run is diffed against the one before, and what changed becomes a finding — a
new lethal trifecta, a model call that lost its governance, a new tool or MCP server, a new
destructive endpoint, an MCP server whose tools drifted. A finding closes itself when its condition
clears and reopens if it comes back; a run that could not read the source closes nothing.

```bash
agentfox scan monitors list                       # what is watched, last outcome, next run
agentfox scan monitors add github_repo acme/bot   # or created for you when you connect one
agentfox admin jobs run-due                       # self-hosted: put this on cron
```

A fourth kind, `deployed_agent`, sends the live probe library to a deployed agent you have opted in
(`/api/probes`); it runs daily, and `AGENTFOX_LIVE_PROBES_ENABLED=false` turns every target off at once.

Findings go out through the signed finding webhook (`AGENTFOX_WEBHOOK_URL`, `AGENTFOX_WEBHOOK_SECRET`)
and, with `AGENTFOX_SLACK_WEBHOOK_URL` set, to Slack, both only with `AGENTFOX_ALLOW_EGRESS=true`.
Push-triggered runs need a webhook secret: `AGENTFOX_GITHUB_WEBHOOK_SECRET`, or one set on the
connection. The hosted runner is triggered by
[`.github/workflows/monitors.yml`](../.github/workflows/monitors.yml) every 30 minutes (secrets
`AGENTFOX_API_URL` and `AGENTFOX_CRON_SECRET`; without them it does nothing).

## Commands, grouped by what you are trying to do

`agentfox --help` lists eleven top-level commands in six groups: Start (`init`, `demo`), See (`scan`,
`agents`), Watch (`serve`, `findings`), Contain (`permit`, `declare`, `policy`), Prove (`test`,
`report`) and Operate (`doctor`, `admin`). Below, the same commands by task.

Every decision lands in a tamper-evident audit chain and maps to the controls you answer to.
Evidence packages ship with a stdlib-only `verify_chain.py`, so an auditor re-derives the hash chain
without trusting us or calling our API.

**Find out what you already have**

```bash
agentfox scan --sessions               # zero-config first look, nothing leaves this machine
agentfox scan                          # scan a repo: tools, MCP servers, the lethal trifecta, ungoverned calls
agentfox agents list                   # every agent, registered or shadow, and who owns it
agentfox scan runtime                  # sweep for shadow agents, drift and identity posture
agentfox agents lineage payments-ops   # what one agent reaches: its blast radius
agentfox scan mcp                      # every MCP server in .mcp.json: reach, pinning, auth; nothing started
agentfox scan mcp fetch --file tools.json   # one server, plus each tool in its real tools/list
```

`scan mcp` exits 1 on a critical finding (a poisoned tool description, a critical config issue or a
lethal trifecta), and `scan --fail` exits non-zero when a repository has an ungoverned model call,
so either can fail a CI step.

**Bound what an agent is allowed to do**

Watch, propose, approve. Let the agent run; default deny refuses and records every call. Then:

```bash
agentfox policy proposals from-traffic --agent support-triage   # declarations + grants, from its calls
agentfox policy proposals approve <id> --actor you@example.com --note "matches its job"
agentfox policy proposals apply <id> --actor you@example.com    # rollback <id> undoes it
```

Each proposal reads like "Let support-triage call tickets.close with priority one of low, normal
(seen 14 times)". Limits and the provenance ceiling come only from clean calls: ones nothing flagged and
that carried no untrusted content, or that a person approved in the approval queue. An injected
call is held like any untrusted one, so an attacker's amount or recipient never becomes a limit. Nothing is applied without a person, and tool
declarations, which are org-wide, need two. Or write them by hand:

```bash
agentfox declare tool billing.export --impact write    # read | write | high_impact | irreversible
agentfox declare tool crm.lookup --impact read --output-trust trusted   # its output is yours
agentfox permit grant support-triage tickets.close \
    --limit priority:in=low,normal --max-taint user
agentfox permit list support-triage                    # anything not listed is refused
agentfox permit revoke <capability-id>
```

`--max-taint` is the worst provenance an argument may carry and still go through without an
approval: `none`, `user`, `retrieved`, `tool_result`, `subagent`, `memory`. Within it, the taint
rules defer to the grant; `composition.escalation` (one tool's output fed into a higher-impact tool)
does not, unless the producing tool's output is declared trusted. `permit grant` is the only
command that widens least privilege, so it confirms before it writes and records the result in the
audit chain. `--yes` skips the prompt in CI. `agentfox agents register <slug> --owner you@example.com` turns a
shadow agent into an owned one, and `agentfox agents budget` sets the caps `budget.exceeded` blocks on.
Whether provenance is read per run or per argument is
one setting, `taint_scope` (`session`, the default and what every number here was measured under,
or `argument`); see [Getting started](getting-started.md#5b-let-it-propose-the-grants-learned-permissions).

**Decide what is held for a person**

```bash
agentfox permit approvals list         # calls waiting for a person; unanswered ones expire, and expiry denies
agentfox permit approvals show <id>    # the call, its arguments, why it was held
agentfox permit approvals approve <id> --rationale "checked the refund"   # the retry runs, once
agentfox permit approvals deny <id>
```

`list` accepts the short id it prints. The agent can read its own approval at
`GET /api/approvals/{id}` with its own key, or wait on it with `fox.wait_for_approval(id)` in Python.
Approving is refused while the agent is killed or quarantined.

**See what happened**

```bash
agentfox report                        # one page for whoever signs off: what ran, what was
                                       # contained and why, what observe mode would have stopped
agentfox findings                      # what the platform found; --severity high to narrow
agentfox doctor                        # is the runtime configured the way you think it is?
agentfox report verify                 # re-derive the chain; exits 1 if broken
agentfox report evidence --agent support-triage --from 2026-08-01 --to 2026-09-30
```

A refused tool call is a finding in its own right, titled by what refused it — `support-bot tried
to send_email with data that came from a web page (contained)` — and one a rule in observe mode
only recorded reads `would have been contained`. The evidence zip opens on the same one-page
`SUMMARY.md` (and `.html`) that `agentfox report` prints; its framework-coverage section is a
draft mapping and says so in its heading.

**Test before you trust**

```bash
agentfox test run support-quality      # score a suite
agentfox test gate support-quality     # CI gate; exits 1 on a regression or any errored case
agentfox test redteam support-triage   # probe the deployed configuration; exits 1 if an attack got through
agentfox policy lint                   # exits 1 on critical or high findings
agentfox policy validate candidate.yaml          # parse, lint and compile without saving; exits 1 on failure
agentfox policy simulate --file candidate.yaml   # replay recorded traffic; non-zero if it newly blocks
```

Red-team probes are a dry run: their tool calls are evaluated without writing decisions, so they
never show up in findings or in what `policy simulate` replays. `--allow-escapes` reports without
failing.

Saving a policy and putting it in force are separate. A version saved in the dashboard's editor or
with `POST /api/policies` sits next to the live one and changes nothing until it is promoted;
promoting it to enforce over HTTP needs a recorded simulation of that exact version (409 otherwise).
`agentfox policy enforce <key>` and `observe <key>` change the live version's mode from the CLI.

**Run it**

```bash
agentfox serve                         # gateway + control-plane API
agentfox admin users create you@example.com --role owner   # the first operator, no demo data
agentfox admin auth issue you@example.com  # mint an API token
agentfox admin db upgrade              # apply migrations
agentfox admin jobs run-due            # one pass of scheduled work (monitors, drift, compliance); put it on cron
agentfox policy effective --agent support-triage  # what is in force, and where each rule came from
agentfox report status --framework eu-ai-act
agentfox agents quarantine support-triage --reason "investigating"   # kill switch, reversible
agentfox agents kill support-triage    # stop it now
agentfox agents resume support-triage
```

## What the demo prints

Real output from `agentfox init && agentfox demo`, trimmed. Step 3 is the one worth reading: the
injection has already succeeded, and the transfer is refused anyway:

```
  transfer, argument from the user  enforced=allow  policy-would=escalate  12.9ms
      eu.art14.human_oversight → escalate  eu-ai-act-high-risk is in observe

  transfer, recipient from the poisoned document  enforced=escalate  policy-would=escalate  4.6ms
      taint.irreversible_tool → escalate  tool-containment is in enforce
        Irreversible tool invoked with arguments originating in untrusted content (retrieved document, tool result or
      capability.approval_required → escalate  tool-containment is in enforce
        arguments ['to'] carry provenance above the capability's max_taint 'user' (to from tool_result), so a person m
  → suspended pending human approval (apr_01m48cfawhd0qv8mr1)

  transfer above the capability's argument constraint  enforced=block  policy-would=block  5.2ms
      capability.constraint_violated → block  tool-containment is in enforce
        agent:payments-ops holds a grant for 'payments.transfer', so this is not a missing permission. The grant allow
```

Three calls, three outcomes, none decided by a detector. The first is clean. The second is identical
except that one argument came out of the poisoned document, so it stops for a human. The third
exceeds the argument limit written into the capability.

Step 10 verifies the audit chain, edits an entry directly in the database, and verifies again:

```
  chain: 14 entries, head seq 14
  verification: INTACT  (14 entries checked)
  after editing entry 3 directly in the database: TAMPERED
      seq 3 · payload_mismatch — payload does not match its recorded digest
```

## Threat coverage and judgment posture

**Threat coverage is a page, not a claim.** Every entry in the OWASP LLM Top 10, OWASP
Agentic T1–T15 and the runtime-reachable part of MITRE ATLAS, with what this deployment
actually does about each one: which detectors watch for it, which rules act on it and
whether they are enforcing or only observing, what was caught, and what the red team got
through. A threat counts as covered only when a rule is *enforcing* — observe mode stops
nothing, and a product that counted it would let a fresh install report full coverage
while blocking nothing. Threats with no control mapped to them appear as gaps rather
than not appearing at all.

Which tiers run, and what may leave the machine, is editable in the product — Policies →
Judgment posture — with the deployment acting as a ceiling the product cannot raise. An admin
can tighten personal-data handling or turn a hosted tier off; nobody can enable one on a
deployment whose `AGENTFOX_ALLOW_EGRESS` is false, and attempting it is a refusal with a reason
rather than a preference that silently does nothing. Every change is recorded with who, why and
what it was before. [What each tier may decide](architecture/judgment-tiers.md), and [what leaves the machine](architecture/judgment-egress.md) when a hosted tier is on.

## Model-backed detectors

**Model-backed detectors need their weights fetched first, on purpose.** None of them downloads
anything while handling a request — a detector whose weights are absent reports itself
unavailable rather than reaching the network mid-decision, and `agentfox doctor` names the one
that is missing. Fetch them deliberately:

```bash
python -m spacy download en_core_web_lg   # pii.presidio — ~400MB
```

Granite Guardian, the injection classifier and the embedding detector pull their weights from
Hugging Face the same way; `agentfox doctor` lists which are present. The running container never
does this itself.

## Architecture, and what is ours

Six pillars: discovery and registry; identity, access and authorisation; runtime guardrails;
evaluation and reliability; audit and traceability; policy and compliance.

Roughly 20% of the engineering integrates OSS primitives — OPA/Rego, Presidio, Granite Guardian,
NeMo/Guardrails AI, promptfoo, Garak, PyRIT, OpenTelemetry — and 80% is the logic above them. Every
wrapped project sits behind a swappable adapter. The [high-level design](architecture/high-level-design.md) has the full design.

Twenty [Guardrails AI Hub](https://guardrailsai.com/hub) validators are wrapped one-per-detector, so
each has its own key, its own measured precision and latency on your traffic, and its own
suppressions — and reports into this project's entity taxonomy, so a jailbreak one of them finds
fires the same policy rule as one ours finds, with no new rule to write. Hub validators carry
licences independent of that project's Apache-2.0 core, so none ships enabled; the dashboard lists
each with the one `pip install` that turns it on. Their telemetry is switched off before any of them
runs — enabling a check must not start exporting spans to a third party from a tool whose first
promise is that it does not phone home.

## Self-hosting

Everything runs on your own infrastructure. There is no licence check, no phone-home, and no
default egress: a fresh install ships with `AGENTFOX_ALLOW_EGRESS=false` and the `echo` provider,
so it runs end to end with no model and no API key. Point it at a model when you want one.

Settings are `AGENTFOX_*` environment variables. The full list is
[plugins/shared/reference/config.md](../plugins/shared/reference/config.md).

**Two secrets are required outside development.** With `AGENTFOX_ENVIRONMENT` set to anything but
`development`, `dev`, `test`, `testing` or `local`, the gateway refuses to start until
`AGENTFOX_SERVICE_AUTH_SECRET` (authenticates the dashboard's call that mints an owner token; the
dashboard needs the same value) and `AGENTFOX_AUDIT_SIGNING_KEY` (signs the audit chain's checkpoints;
keep a copy outside the database) are set to values that are not the published defaults.
`openssl rand -hex 32` makes either. `agentfox doctor` has a `secrets` line that says where you stand.

**Nothing seeds itself.** A new deployment has no demo data, no operators and no policy packs bound
(only built-in default deny on tool calls). Run `agentfox init` against its database once to load the
control catalogue and the packs. Create the first operator with `agentfox admin users create you@example.com --role owner --token`, then sign in to the
dashboard with "Self-hosted? Sign in with an API token"; signing out revokes the token. `agentfox
admin seed` loads the demo agents and traffic, deliberately and only where you want them.

**Scheduled work needs a scheduler.** Monitors, drift, compliance and canaries run as jobs.
Self-hosted, put `agentfox admin jobs run-due` on cron or a systemd timer every 10 to 30 minutes; it is
safe to run as often as you like.

The public `/live` showcase is off unless `AGENTFOX_SHOWCASE_ENABLED=true`; only the hosted
deployment behind the website runs it.

Set `AGENTFOX_CONSOLE_URL` to wherever your dashboard is reachable and every governed response
carries an `explain_url` — and an `X-AgentFox-Explain` header — pointing at the decision it
describes, so a block in a log is one click from the reason for it. It is left empty by default
and never inferred from the request: behind a proxy the `Host` header is whatever the proxy sent,
and a link to somewhere that does not exist is worse than no link.

**1. One click** — provisions Postgres, the gateway and the dashboard, wired together:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/architsharm/agentfox)

The blueprint is [`render.yaml`](../render.yaml). The gateway needs Render's `starter` instance type
rather than `free` — the image carries the classifier extra — and the blueprint says so rather than
letting you find out on a failed build. The database and the dashboard run on free. Render generates
both required secrets for you.

**2. Docker Compose** — the whole stack, including OPA, on one machine:

```bash
git clone https://github.com/architsharm/agentfox.git && cd agentfox
docker compose -f deploy/docker-compose.yml up -d
# dashboard on :3000, gateway on :8080
```

It pulls prebuilt images rather than building them —
[`ghcr.io/architsharm/agentfox/gateway`](https://github.com/architsharm/agentfox/pkgs/container/agentfox%2Fgateway)
and
[`ghcr.io/architsharm/agentfox/dashboard`](https://github.com/architsharm/agentfox/pkgs/container/agentfox%2Fdashboard),
Compose pulls `:latest`, which moves on each `v*` release tag; `:edge` tracks `main` if you want
unreleased changes. `docker compose build` builds from source instead, which takes a while: the
gateway image pre-fetches 1–2GB of permissive-licence detector weights so the running container
never needs network access for them. The licence-gated Llama Guard tier is off by default and is
never in the published image; the compose file's header has the opt-in steps.

[`deploy/docker-compose.yml`](../deploy/docker-compose.yml) is commented line by line. It runs the
gateway in `production`, so export `AGENTFOX_SERVICE_AUTH_SECRET` and `AGENTFOX_AUDIT_SIGNING_KEY`
(or put them in `deploy/.env`) before `up`; Compose stops with a message if either is missing. Then
load the packs and create the first operator inside the container:

```bash
docker compose -f deploy/docker-compose.yml exec gateway agentfox init
docker compose -f deploy/docker-compose.yml exec gateway \
  agentfox admin users create you@example.com --role owner --token
```

**3. Python, no containers** — the gateway is an ordinary ASGI app:

```bash
pip install "agentfox[postgres]"
agentfox init                      # SQLite by default; set AGENTFOX_DATABASE_URL for Postgres
export AGENTFOX_ENVIRONMENT=production
export AGENTFOX_SERVICE_AUTH_SECRET="$(openssl rand -hex 32)"
export AGENTFOX_AUDIT_SIGNING_KEY="$(openssl rand -hex 32)"   # keep a copy
agentfox admin users create you@example.com --role owner --token
uvicorn agentfox.apps.gateway.app:app --host 0.0.0.0 --port 8080
```

For a reboot-persistent gateway service, see the [systemd deployment guide](deployment/systemd.md).

**After any of them:** create a GitHub OAuth app and set its callback to
`https://<your-host>/api/auth/github/callback`. The dashboard runbook is
[`deploy/README-dashboard.md`](../deploy/README-dashboard.md); a Fly.io config, with its commands in
its own header, is [`deploy/fly.dashboard.toml`](../deploy/fly.dashboard.toml).
