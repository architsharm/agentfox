# Getting started

A linear first hour with AgentFox, from an empty directory to one of your own agents under
enforcement. Every command here was run before it was written down. Each step says what it proves,
because a governance tool that you cannot check is a governance tool you should not trust.

If you would rather see the product work before installing anything, the hosted playground needs no
account: <https://useagentfox.com/playground>.

**You need:** Python 3.11 or newer, and a terminal. Nothing else. Every step below runs offline:
no API key, no model weights, no network egress. The built-in `echo` model provider makes the whole
enforcement path demonstrable with nothing installed.

**Vocabulary used throughout:**

- **Agent**: a program that calls a model and can take actions. AgentFox identifies each one by a
  slug such as `support-triage`.
- **Tool**: something an agent can call that is not the model: a function, an API, an MCP server
  method. Each tool is declared with an **impact** of `none`, `read`, `write` or `irreversible`.
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
python3 -m venv .venv && source .venv/bin/activate
pip install agentfox
agentfox --help
```

AgentFox is not on PyPI yet, so install from git. The core install is deliberately light: it pulls
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
  ✓ database ready
  ✓ 43 controls across 7 frameworks  v0.1.0-draft (draft)
  ✓ 4 policy pack(s) loaded
      baseline                 observe  recorded, nothing blocked
      coding-agent             observe  recorded, nothing blocked
      eu-ai-act-high-risk      observe  recorded, nothing blocked
      tool-containment         enforce  violations are blocked now
```

This creates a SQLite database in the current directory, loads the control catalogue and four
policy packs, and writes a `agentfox.toml` if there isn't one. It is idempotent and offline, so it
is safe to run again.

Read the mode column carefully, because it is the whole shape of the product. The three
detector-driven packs start in **observe**: they record what they would have done and block
nothing. `tool-containment` starts in **enforce**, because it does not guess. It refuses calls that
no capability grants, and calls that carry untrusted arguments into an irreversible tool. Those are
structural facts, not classifier scores, so they can block on day one without producing false
positives that get the whole thing switched off.

**What this proves:** the control plane exists locally, with no service to sign up for, and the one
layer that blocks from the start is the one that does not rely on detection.

---

## Step 3. Scan a repository (5 minutes)

Point it at a codebase you actually work on.

```bash
cd /path/to/your/project
agentfox check
```

```
╭─ CRITICAL · lethal trifecta ─────────────────────────────────────────────────╮
│ bot.py: can read customer records (read_customer_record), reads untrusted    │
│ web pages (fetch_url), and can send email (send_email) or can move money     │
│ (issue_refund). An instruction hidden in a web page could send customer data │
│ out.                                                                         │
│                                                                              │
│ Contain it: `agentfox capability grant <agent> send_email --max-taint user`  │
│ (...), or run with `agentfox.auto(mode="observe")` to watch it happen.       │
╰─ private data + untrusted content + a way out ───────────────────────────────╯
Scanned 2 files in /path/to/your/project
  built on: OpenAI SDK

  1 of 1 model call sites are ungoverned  (0% covered)
  can reach: 4 tools · 2 MCP servers (filesystem, fetch)
     read_customer_record  bot.py     private data
     fetch_url             bot.py     untrusted input
     send_email            bot.py     sends out / irreversible
     ...
```

It is a static read of the source. It finds every place the code calls a model, every tool —
decorated functions, OpenAI function schemas (`tools=[{"type": "function", ...}]`, inline or in a
list passed later) and Anthropic tool dicts (`name` + `input_schema`) — every MCP server your client
configs declare, hard-coded credentials, and shell and SQL construction near model output. It writes
nothing to your project and sends nothing anywhere.

Each tool and MCP server is classified by what it can do: read private data, read content someone
outside can write, or send data out / act irreversibly. Where one agent has all three — tools grouped
by directory, MCP servers by the config file that loads them together — that is the **lethal
trifecta** (Simon Willison's term), and it is printed first, as a sentence you can forward, with the
command that contains it. The classification comes from names and descriptions, so a tool named
`do_thing` is left unflagged rather than guessed at, and an MCP server AgentFox does not recognise is
reported as unknown, never as safe. `--json` carries the same data as flags (`private_data`,
`untrusted_input`, `exfiltration`).

To look closer at the MCP servers, `agentfox scan mcp` reads the same configs, registers every
server, and reports reach, version pinning and remote auth for each without starting any of them.

For a first look at a machine you have not installed anything on, `agentfox quickscan` does the
same thing plus a scan of local AI-tool session transcripts, and runs a handful of known-adversarial
prompts through the real detector pipeline in your terminal, so "we catch prompt injection" is
something you watch happen rather than something we said.

**What this proves:** you get an inventory before you get an opinion. Most teams do not have a list
of where their code talks to a model.

---

## Step 4. Watch the whole thing work (5 minutes)

```bash
agentfox demo
```

Thirteen steps in about five seconds, against a seeded environment of three agents. The step to
read closely is step 3, where the injection has already succeeded and the transfer is refused
anyway. The README walks through the output:
[what the demo actually prints](../README.md#what-the-demo-actually-prints).

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
  "rules_fired": [{ "rule_id": "capability.denied",
                    "reason": "no resolved identity for the caller, so it holds no grants (default deny). To have grants proposed from the calls this agent has made, run `agentfox proposals from-traffic` and approve them; to grant this one directly, `agentfox capability grant <agent> payments.transfer`." }] }
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
agent     env         risk     registered  owner    framework
my-agent  production  limited  SHADOW      unowned  —
  1 agents · 1 shadow · 1 unowned · 1 lineage edges
```

The agent registered itself as **shadow** traffic, from the call, without anyone filling in a form.
`agentfox findings` shows the matching `shadow_agent` finding.

### 5b. Let it propose the grants (learned permissions)

You can write every declaration and grant by hand (5c). You do not have to. Let the agent run for
a while as it is: every refused call is recorded with its tool, its arguments and where each
argument came from. Then:

```bash
agentfox proposals from-traffic --agent my-agent        # --since 7d to narrow the window
```

```
read 21 tool call(s): 10 benign, 11 held for provenance, 0 flagged
filed 8, refreshed 0, superseded 0, verified 0
  chp_…  tool.declare · proven
      Declare issue_refund as irreversible (called 5 times by support-bot, never declared; impact guessed from its name)
  chp_…  capability.grant · proven
      Let support-bot call issue_refund with amount ≤ 120 (seen 5 times, max 112)
  chp_…  capability.grant · proven
      Let support-bot call send_email with to at example.com or example.org (seen 6 times)
  …
```

Read one with `agentfox proposals show <id>`, then approve and apply it:

```bash
agentfox proposals approve <id> --actor you@example.com --note "matches its job"
agentfox proposals apply <id> --actor you@example.com
```

What it will and will not learn from is the part to understand:

- **Learned from:** calls refused only because no grant existed, the tool was undeclared, or no
  intent was declared. Those say nothing about the call, only about your configuration.
- **Held:** calls stopped for where their arguments came from (`taint.*`, `composition.escalation`),
  or carrying untrusted content into a tool whose impact nobody had declared yet. An injected call
  looks exactly like this, so held calls shape the argument limits but never the provenance
  ceiling. Once the grant exists, calls like them are escalated to the approval queue. Approve the
  ones that are fine there, and the next `from-traffic` proposes raising that grant's ceiling.
- **Never learned from:** a call a detector matched (an injection, a credential; personal data in
  an email address is not an attack), a call over an existing grant's limit, or one a person denied.

Every proposal widens what an agent may do, so none is ever applied by automation. Grants are
scoped to one agent and need one approver. Tool declarations apply to the whole organisation, so
they need two different people. `agentfox proposals rollback <id>` undoes either. The scheduler
runs the same loop daily (`grants.propose`); it files, a person decides.

**When the report says composition.** A value an agent copies out of one tool's output into a
higher-impact tool is blocked as `composition.escalation`: a CRM lookup's email address passed to
`send_email` looks exactly like an attacker's address scraped from a web page. If the producing
tool is a system of record you control, say so, and values copied out of it stop counting as
untrusted input:

```bash
agentfox tools declare read_customer_record --impact read --output-trust trusted
```

Output is untrusted unless you declare otherwise.

**Session or argument provenance.** One setting decides what a tool call's provenance is:
`taint_scope` in `agentfox.toml` (or `AGENTFOX_TAINT_SCOPE`). `session`, the default, is the worst
untrusted content anywhere in the run so far: once the agent has read a web page, every later
irreversible call carries it, including a refund with no arguments at all. `argument` is only what
the call's own arguments were copied from. Session contains more attacks and escalates more
legitimate calls; argument lets more legitimate work through and misses an attack whose payload
never lands in an argument. Every published number was measured under `session`.

### 5c. Declare the tool and grant the capability by hand

```bash
agentfox tools declare payments.transfer --impact irreversible
agentfox capability grant my-agent payments.transfer \
    --limit amount:lt=1000 --max-taint user
```

`capability grant` is the only command that widens least privilege, so it prints exactly what it is
about to allow and asks before it writes, then records the grant in the audit chain. Pass `--yes`
in scripts. `--max-taint user` means: arguments a person typed are fine, anything that came out of
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

An `escalate` verdict returns an `approval_id`. Poll `GET /api/approvals/{id}`, or decide it from
the dashboard or the CLI.

### 5d. Proxy the model call too (optional)

If you want the model traffic traced and evaluated as well, point your existing OpenAI or Anthropic
client's `base_url` at `http://localhost:8080/v1` and change nothing else. The response carries the
decision in headers:

```
x-nometria-trace: trc_01m376q450vgp786rg
x-nometria-verdict: allow
x-nometria-effective-verdict: allow
x-nometria-mode: enforce
x-nometria-latency-ms: 2.72
```

`x-nometria-verdict` is what happened. `x-nometria-effective-verdict` is what the policy would have
done regardless of mode. In observe mode they differ, and that gap is the thing you watch before
turning enforcement on.

Useful request headers: `X-Nometria-Agent` (the agent slug), `X-Nometria-Session` (correlates calls
into one execution path), `X-Nometria-Intent` (the declared task, used by intent-based containment),
and `X-Nometria-Trust` (a JSON map marking message indices as untrusted, e.g.
`{"2":"retrieved"}`). Full surface: [Appendix C](appendix-c-api-spec.md).

**If you are in Python instead**, the whole of 5d is one line at your entry point:

```python
import agentfox
agentfox.auto()
```

It governs more than the gateway does from the same position: besides the request and the response
text, every tool call in the response (OpenAI `tool_calls`, Anthropic `tool_use`, streamed or not)
goes through the tool-call check before the response is handed back, with argument provenance read
from the conversation. A tool it has not seen before is registered with an inferred impact —
`agentfox tools list` marks it `(inferred)` until you confirm it with `agentfox tools declare`. In
the default mode a refused tool call raises `agentfox.Blocked`, except that capability default-deny
only applies once the agent holds a grant; `auto(mode="observe")` records and never raises. The
OpenAI Responses API is not patched.

**What this proves:** enforcement is a property of the deployment, not of your codebase, and an
undeclared agent is refused before anybody writes a rule about it.

### 5e. A token for the control-plane API

The `/v1/guard/*` endpoints above read no credential. The control-plane API under `/api` does:

```bash
agentfox auth issue you@example.com --name "ci"
curl -H "Authorization: Bearer nom_api_..." http://localhost:8080/api/findings
```

One honest caveat: `auth issue` mints a token for an operator that already exists, and a database
created by `agentfox init` alone has no operators in it. Today the first operator account comes
from `agentfox seed` (which creates `admin@example.com` and four other roles) or from signing in to
the dashboard with GitHub. Token values are shown once, hashed at rest with argon2id, and carry an
expiry. `agentfox auth status` tells you whether this deployment is actually requiring them: in a
development environment it accepts an `X-Nometria-User` header instead, which is fine locally and
unacceptable anywhere else.

---

## Step 6. Read what it found (10 minutes)

```bash
agentfox findings
agentfox findings --severity high
agentfox doctor
```

`findings` is the list of things a person should look at: shadow agents, agents with no accountable
owner, stale identities, and every detection that led to a block or a redaction.

`doctor` is the more interesting one, because it grades the configuration rather than the traffic:

```
  ✓    database            reachable — 4 agent(s), 4 trace(s)
  ✓    enforcement         25 of 25 decisions enforced
  !    authentication      the X-Nometria-User header is accepted, anyone who can reach
                           this port is any user they name. Fine locally, unacceptable
                           anywhere else.
  ✓    containment         11 of 16 tool(s) can act, 15 capability grant(s)
  ✓    detectors           8 available
  !    detector failure    fail-open: a detector that times out lets the request through
                           and records the gap
  !    findings            9 open — run `agentfox findings`
```

Note the two lines marked `!` that are not about your agents at all. AgentFox tells you that it
fails open, and that your auth mode is a development mode, rather than leaving you to discover it.

Three commands worth knowing here:

```bash
agentfox agents lineage my-agent     # what this agent reaches: its blast radius
agentfox capability list my-agent    # what it may do; anything not listed is refused
agentfox audit verify                # re-derive the tamper-evident chain; exits 1 if broken
```

**What this proves:** the platform reports its own gaps, including the ones that are inconvenient
for it.

---

## Step 7. Test before you trust (10 minutes)

Two things worth running before you turn enforcement on.

```bash
agentfox redteam run my-agent
```

Fires the built-in adversarial probe suite (mapped to OWASP LLM Top 10 and MITRE ATLAS) at this
deployment's actual capability grants and policy bindings, and reports what got through. It
includes benign controls, so a configuration that blocks everything scores badly rather than
perfectly. Read the result as configuration regression testing: it tells you whether *this
deployment* got weaker, and it is not a robustness certificate.

```bash
agentfox policy simulate --file candidate.yaml
```

Replays the traffic already recorded in your database against a candidate policy, so you can see
what a rule change would have done before it does it.

If you have an eval suite, `agentfox eval gate <suite>` exits 1 on regression and is meant to run
in CI.

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

If it goes wrong, `agentfox policy observe baseline` demotes it again, and
`agentfox agents quarantine <agent> --reason "..."` stops one agent without touching the rest. Both
are reversible and both are audited.

**What this proves:** enforcement is one deliberate, reversible, audited step, taken after you have
seen what it will do.

---

## Where to go next

- **[docs/README.md](README.md)**: what every other document in this directory is for.
- **[Appendix C](appendix-c-api-spec.md)**: the full API, including the routes the dashboard
  itself uses. There is no privileged back-channel.
- **[The benchmarking white paper](benchmarking-whitepaper.md)**: how each capability was measured,
  including where it loses.
- **[How to read our numbers](evidence-standards.md)**: read this before quoting any benchmark
  result anywhere.
- **[`harness/`](../harness/README.md)**: drive all of the above from Claude Code or another coding
  agent, if you would rather not learn the command list.
- **[Appendix E](appendix-e-threat-model.md)**: the threat model, including threats to AgentFox
  itself.

Two things to keep in mind as you go further. Containment is exactly as good as the declarations
behind it: a destructive tool declared `read` will not be treated as destructive by anything
downstream, which is why `agentfox doctor` grades your declarations and `agentfox check` finds the
tools you have not declared. And compliance mappings ship as engineering drafts, labelled
`DRAFT — UNVERIFIED / NOT LEGAL ADVICE` inside evidence packages, until a qualified reviewer signs
them off.
